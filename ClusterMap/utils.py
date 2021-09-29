import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from scipy.stats import spearmanr
from sklearn.neighbors import NearestNeighbors, KNeighborsClassifier
from itertools import product
from fastdist import fastdist
from tqdm import tqdm
    
def NGC(self,spots):
    
    '''
    Compute the NGC coordinates

    params :    - radius float) = radius for neighbors search
                - num_dim (int) = 2 or 3, number of dimensions used for cell segmentation
                - gene_list (1Darray) = list of genes used in the dataset
    
    returns :   NGC matrix. Each row is a NGC vector
    '''
    radius=max(self.xy_radius,self.z_radius)
    if self.num_dims == 3:
        X_data = np.array(spots[['spot_location_1', 'spot_location_2', 'spot_location_3']])
    else:
        X_data = np.array(spots[['spot_location_1', 'spot_location_2']])
    knn = NearestNeighbors(radius=radius)
    knn.fit(X_data)
    spot_number = spots.shape[0]
    res_dis,res_neighbors = knn.radius_neighbors(X_data, return_distance=True)
    ### remove nearest spots outside z_radius
    if radius==self.xy_radius:
        smaller_radius=self.z_radius
    else:
        smaller_radius=self.xy_radius
    for indi,i in tqdm(enumerate(res_neighbors)):
        res_neighbors[indi]=i[X_data[i,2]-X_data[indi,2]<=smaller_radius]
        res_dis[indi]=res_dis[indi][X_data[i,2]-X_data[indi,2]<=smaller_radius]
    
    res_ngc = np.zeros((spot_number, len(self.gene_list)))
    for i in range(spot_number):
        neighbors_i = res_neighbors[i]
        genes_neighbors_i = spots.loc[neighbors_i, :].groupby('gene').size()
        res_ngc[i, genes_neighbors_i.index.to_numpy() - np.min(self.gene_list)] = np.array(genes_neighbors_i)
        # res_ngc[i] /= len(neighbors_i)
    return(res_ngc)

def add_dapi_points(dapi_binary,dapi_grid_interval, spots_denoised, ngc, num_dims):
    
    '''
    Add sampled points for Binarized DAPI image to improve local densities

    params :    - dapi_binary (ndarray) = Binarized DAPI image
                - spots_denoised (dataframe) = denoised dataset
                - nodes (list of ints) = nodes of the StellarGraph
                - node_emb (ndarray) = node embeddings
    returns :   - spatial locations and ngc of all the points

    '''
    ### Sample dapi points
    sampling_mat = np.zeros(dapi_binary.shape)
    if num_dims==3:
        for ii,jj,kk in product(range(sampling_mat.shape[0]), range(sampling_mat.shape[1]),range(sampling_mat.shape[2])):
            if ii%dapi_grid_interval==2 and jj%dapi_grid_interval==2 and kk%dapi_grid_interval==2:
                sampling_mat[ii,jj,kk] = 1
        dapi_sampled = dapi_binary*sampling_mat
        dapi_coord = np.argwhere(dapi_sampled > 0)
        spots_points = spots_denoised.loc[:, ['spot_location_2', 'spot_location_1', 'spot_location_3']]
    else:
        for ii,jj in product(range(sampling_mat.shape[0]), range(sampling_mat.shape[1])):
            if ii%dapi_grid_interval==2 and jj%dapi_grid_interval==2:
                sampling_mat[ii,jj] = 1
        dapi_sampled = dapi_binary*sampling_mat
        dapi_coord = np.argwhere(dapi_sampled > 0)
        spots_points = spots_denoised.loc[:, ['spot_location_2', 'spot_location_1']]


    knn = NearestNeighbors(n_neighbors=1)
    knn.fit(spots_points)
    neigh_ind = knn.kneighbors(dapi_coord, 1, return_distance=False)
    
    ### Create dapi embedding thanks to the embedding of the nearest neighbor
    dapi_ngc = ngc[neigh_ind[:,0]]
    
    ### Concatenate dapi embedding + <x,y,z> with spots embedding + <x,y,z>
    all_ngc = np.concatenate((ngc, dapi_ngc), axis=0)
    all_coord = np.concatenate((spots_points, dapi_coord), axis=0)
    return(all_coord, all_ngc)

def spearman_metric(x,y):
    '''
    Compute the spearman correlation as a metric
    '''
    return(spearmanr(x,y).correlation)

def reject_outliers(data, m=3):
    '''
    Remove outliers. An outlier is a value that is more than three scaled median absolute deviations (MAD) away from the median.
    '''
    test=abs(data-np.median(data,axis=0)) < m* np.std(data, axis=0)
    list=[i[0] and i[1] for i in test]
    return(data[list,:])


def DPC(self,all_coord, all_ngc, cell_num_threshold, spearman_metric=spearman_metric,use_genedis=True):    
    
    '''
    Density Peak Clustering

    params :    - ngc (ndarray) = NGC vectors for each spot
                - spearman_metric (callable) = metric to use in the computation of genetic distance
    '''
    #find nearest spots within radius and Compute spatial distance
    # add: consider z radius
    print('  Compute spatial distance')
    radius=max(self.xy_radius,self.z_radius)
    knn = NearestNeighbors(radius=radius)
    knn.fit(all_coord)
    spatial_dist, spatial_nn_array = knn.radius_neighbors(all_coord,sort_results=True) 
    if radius==self.xy_radius:
        smaller_radius=self.z_radius
    else:
        smaller_radius=self.xy_radius
    for indi,i in tqdm(enumerate(spatial_nn_array)):
        spatial_nn_array[indi]=i[all_coord[i,2]-all_coord[indi,2]<=smaller_radius]
        spatial_dist[indi]=spatial_dist[indi][all_coord[i,2]-all_coord[indi,2]<=smaller_radius]
    
    # Compute genetic distance with nearest spots within radius
    print('  Compute genetic distance')
    NGC_dist=spatial_dist.copy()
    for i,j in tqdm(enumerate(spatial_nn_array)):
        NGC_dist[i]=fastdist.vector_to_matrix_distance(all_ngc[i,:],all_ngc[j,:],fastdist.euclidean, "euclidean")

    #combine two dists
    if use_genedis:
        combine_dist=spatial_dist+NGC_dist/10
    else:
        combine_dist=spatial_dist
    
    #compuete density rho and the nearest distance to a spot with higher density delta
    print('  Compute density rho and the nearest distance')
    rho=[np.exp(-np.square(i/(self.xy_radius*0.4))).sum() for i in combine_dist]
    rho=np.array(rho)
    rho_descending_order=np.argsort(-rho)    
    
    #to find delta and nneigh, compute knn within a large radius
    knn = NearestNeighbors(radius=radius*5)
    knn.fit(all_coord)
    l_neigh_dist, l_neigh_array = knn.radius_neighbors(all_coord,sort_results=True) 

    #find delta and nneigh for spots that exist within the large radius
    delta=np.zeros(rho_descending_order.shape)
    nneigh=np.zeros(rho_descending_order.shape)
    far_higher_rho=[]
    for i,neigh_array_id in tqdm(enumerate(l_neigh_array)):
        try:
            loc=np.where(rho[neigh_array_id]>rho[neigh_array_id[0]])[0][0]
            delta[i]=l_neigh_dist[i][loc]
            nneigh[i]=neigh_array_id[loc]

        except IndexError:
            far_higher_rho.append(i)

    #find delta and nneigh for spots that don't exist within the large radius
    for i in tqdm(far_higher_rho):
        x_loc_i=np.where(rho_descending_order==i)[0][0]
        if x_loc_i>0:
            knn=NearestNeighbors(n_neighbors=1)
            knn.fit(all_coord[rho_descending_order[:x_loc_i],:])
            dis,nearest_id=knn.kneighbors(all_coord[i,:].reshape(1, -1),return_distance=True)
            delta[i]=dis
            nneigh[i]=rho_descending_order[nearest_id]

    #assign delta for the largest density spot
    delta[rho_descending_order[0]]=np.max(delta)
    nneigh[rho_descending_order[0]]=-1    

    #find cluster number
    number_cell=0
    for numbertestid in range(2):
        if numbertestid==0:
            lamda=rho*delta
        else:
            lamda=np.log(rho)*delta
        sort_lamda=-np.sort(-lamda)
        bin_index=range(0,self.num_spots_with_dapi,50)
        start_value=sort_lamda[bin_index][:-1]
        middle_value=sort_lamda[bin_index][1:]
        change_value=start_value-middle_value
        curve=(change_value/(change_value[1]-change_value[-1]))

        for indi,i in enumerate((change_value/(change_value[1]-change_value[-1]))):
            if i<cell_num_threshold  and  curve[indi+1]<cell_num_threshold:
                number_cell=number_cell+(indi)*50
                break
    number_cell=number_cell/2            
    if number_cell==0:
        number_cell=20
        
    self.number_cell=int(number_cell)
    lamda=np.log(rho)*delta*delta
    sort_lamda=-np.sort(-lamda) 
    list12=[x in sort_lamda[:self.number_cell] for x in lamda]
    list12not=[not x for x in list12]
    print(f'  Find cell number:{number_cell}')

    #assign the remaining spots
    cellid=np.zeros((self.num_spots_with_dapi,))-1
    cellid[list12]=range(cellid[list12].shape[0])
    for i_value in tqdm(rho_descending_order):
        if cellid[int(i_value)]==-1:
            if cellid[int(nneigh[int(i_value)])]==-1:
                print('error')
            cellid[int(i_value)]=cellid[int(nneigh[int(i_value)])]

    # Compute spatial distance
#     spatial_dist = np.array(cdist(spatial, spatial, metric='euclidean'), dtype=np.float32)
    
    # Compute genetic distance
#     distances = 1/np.array(cdist(ngc, ngc, metric=spearman_metric), dtype=np.float32)
#     distances *= spatial_dist

    # Compute densities rho
#     densities = np.sum(np.maximum(distances - d_max, 0)*np.exp((-(distances/R)**2), dtype=np.float32), axis=1, dtype=np.float32)
    
#     index_highest_density = np.argmax(densities)
    
    # Compute distance delta (initialize gamma to delta for computation efficiency)
#     gamma = np.array([np.min(distances[i,densities>densities[i]]) if i!=index_highest_density else 0 for i in range(len(densities))], dtype=np.float32)

    # Update gamma
#     gamma[index_highest_density] = distances[index_highest_density,np.argmax(gamma)]
#     gamma *= densities

    # Identify cell centers
#     gamma_sorted = np.sort(gamma)
#     gamma_sorted = gamma_sorted[::-1]
#     spots_sorted_by_gamma = np.argsort(gamma)
#     spots_sorted_by_gamma = spots_sorted_by_gamma[::-1]

    # Find elbow
#     sample_gamma_50 = gamma_sorted[::50]
#     diffs = np.abs(np.diff(sample_gamma_50))
#     ind_thresh = np.argwhere(diffs<100)[0][0]

    # Find the cell centers
#     cell_centers_index = spots_sorted_by_gamma[:50*ind_thresh]

    # Assign the rest of the spots by descending density rho
#     ind_densities_sorted = np.argsort(densities)
#     ind_densities_sorted = ind_densities_sorted[::-1]
#     ind_densities_sorted_remaining_points = ind_densities_sorted[np.setdiff1d(np.arange(len(densities)),cell_centers_index )]

#     ind_spots_assigned = list(np.array(cell_centers_index, copy=True))
#     cell_ids = np.zeros(len(densities))
#     cell_ids[cell_centers_index] = np.arange(1,len(cell_centers_index)+1) 
#     for ind_point in ind_densities_sorted_remaining_points:
#         # Assign the cell label of the nearest spatial neighbor
#         nearest_point = np.argmin(spatial_dist[ind_point, ind_spots_assigned])
#         cell_ids[ind_point] = cell_ids[ind_spots_assigned[nearest_point]]
#         ind_spots_assigned.append(ind_point)

    return(cellid)